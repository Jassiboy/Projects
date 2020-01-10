package Demo.Main;

import java.util.Random;

/**
 * Created by jassiboy on 2/26/2017.
 */
public class RandomGenerator {
    private static Random r;

    public static int getInt(int upperRange) {
        if(r == null) {
            r = new Random();
        }

        return r.nextInt(upperRange);
    }

    public static int getInt(int lowerRange, int upperRange) {
        if(r == null) {
            r = new Random();
        }

        return r.nextInt(upperRange - lowerRange) + lowerRange;
    }
}
